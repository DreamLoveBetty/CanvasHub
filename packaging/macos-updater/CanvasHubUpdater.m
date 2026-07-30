#import <CommonCrypto/CommonDigest.h>
#import <Foundation/Foundation.h>
#import <fcntl.h>
#import <signal.h>
#import <sys/stdio.h>

static NSString *const UpdaterVersion = @"1";
static NSString *const ExpectedBundleIdentifier = @"com.canvashub.desktop";
static NSString *LogFilePath = nil;

static void Log(NSString *message) {
    NSString *timestamp = [[[NSISO8601DateFormatter alloc] init] stringFromDate:[NSDate date]];
    NSString *line = [NSString stringWithFormat:@"[%@] %@\n", timestamp, message];
    fputs(line.UTF8String, stderr);
    if (LogFilePath.length == 0) {
        return;
    }

    NSFileManager *fileManager = [NSFileManager defaultManager];
    [fileManager createDirectoryAtPath:[LogFilePath stringByDeletingLastPathComponent]
           withIntermediateDirectories:YES
                            attributes:nil
                                 error:nil];
    if (![fileManager fileExistsAtPath:LogFilePath]) {
        [fileManager createFileAtPath:LogFilePath contents:nil attributes:nil];
    }
    NSFileHandle *handle = [NSFileHandle fileHandleForWritingAtPath:LogFilePath];
    [handle seekToEndOfFile];
    [handle writeData:[line dataUsingEncoding:NSUTF8StringEncoding]];
    [handle closeFile];
}

__attribute__((noreturn))
static void Fail(NSString *message) {
    @throw [NSException exceptionWithName:@"CanvasHubUpdaterFailure" reason:message userInfo:nil];
}

static NSDictionary<NSString *, id> *ParseArguments(NSArray<NSString *> *arguments) {
    if (arguments.count == 2 && [arguments[1] isEqualToString:@"--version"]) {
        printf("%s\n", UpdaterVersion.UTF8String);
        exit(EXIT_SUCCESS);
    }

    NSMutableDictionary<NSString *, id> *values = [NSMutableDictionary dictionary];
    values[@"relaunch"] = @YES;
    for (NSUInteger index = 1; index < arguments.count;) {
        NSString *argument = arguments[index];
        if ([argument isEqualToString:@"--no-relaunch"]) {
            values[@"relaunch"] = @NO;
            index += 1;
            continue;
        }
        if (![argument hasPrefix:@"--"] || index + 1 >= arguments.count) {
            Fail([NSString stringWithFormat:@"Invalid updater argument: %@", argument]);
        }
        values[argument] = arguments[index + 1];
        index += 2;
    }

    NSArray<NSString *> *required = @[
        @"--parent-pid",
        @"--archive",
        @"--target-app",
        @"--expected-version",
        @"--expected-sha512",
        @"--expected-size",
        @"--state-file",
        @"--log-file",
    ];
    for (NSString *name in required) {
        if ([values[name] length] == 0) {
            Fail([NSString stringWithFormat:@"Missing updater argument: %@", name]);
        }
    }

    pid_t parentPID = [values[@"--parent-pid"] intValue];
    unsigned long long expectedSize = [values[@"--expected-size"] longLongValue];
    if (parentPID <= 0) {
        Fail(@"Invalid parent process id");
    }
    if (expectedSize == 0) {
        Fail(@"Invalid expected archive size");
    }
    values[@"parentPID"] = @(parentPID);
    values[@"expectedSize"] = @(expectedSize);
    values[@"archive"] = [values[@"--archive"] stringByStandardizingPath];
    values[@"targetApp"] = [values[@"--target-app"] stringByStandardizingPath];
    values[@"stateFile"] = [values[@"--state-file"] stringByStandardizingPath];
    values[@"logFile"] = [values[@"--log-file"] stringByStandardizingPath];
    values[@"expectedVersion"] = values[@"--expected-version"];
    values[@"expectedSHA512"] = values[@"--expected-sha512"];
    return values;
}

static NSString *RunTask(NSString *executable, NSArray<NSString *> *arguments, BOOL allowFailure) {
    NSTask *task = [[NSTask alloc] init];
    task.executableURL = [NSURL fileURLWithPath:executable];
    task.arguments = arguments;
    task.environment = @{
        @"HOME": NSHomeDirectory(),
        @"LANG": NSProcessInfo.processInfo.environment[@"LANG"] ?: @"en_US.UTF-8",
        @"PATH": @"/usr/bin:/bin:/usr/sbin:/sbin",
    };
    NSPipe *pipe = [NSPipe pipe];
    task.standardOutput = pipe;
    task.standardError = pipe;
    NSError *launchError = nil;
    if (![task launchAndReturnError:&launchError]) {
        Fail([NSString stringWithFormat:@"%@ failed to launch: %@",
              executable.lastPathComponent, launchError.localizedDescription]);
    }
    NSData *outputData = [pipe.fileHandleForReading readDataToEndOfFile];
    [task waitUntilExit];
    NSString *output = [[NSString alloc] initWithData:outputData encoding:NSUTF8StringEncoding] ?: @"";
    if (task.terminationStatus != 0 && !allowFailure) {
        Fail([NSString stringWithFormat:@"%@ failed with exit code %d: %@",
              executable.lastPathComponent,
              task.terminationStatus,
              [output stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]]]);
    }
    return output;
}

static NSString *ArchiveSHA512(NSString *archivePath) {
    NSFileHandle *handle = [NSFileHandle fileHandleForReadingAtPath:archivePath];
    if (handle == nil) {
        Fail(@"The downloaded update archive cannot be opened");
    }
    CC_SHA512_CTX context;
    CC_SHA512_Init(&context);
    while (YES) {
        @autoreleasepool {
            NSData *data = [handle readDataOfLength:1024 * 1024];
            if (data.length == 0) {
                break;
            }
            CC_SHA512_Update(&context, data.bytes, (CC_LONG)data.length);
        }
    }
    [handle closeFile];
    unsigned char digest[CC_SHA512_DIGEST_LENGTH];
    CC_SHA512_Final(digest, &context);
    NSData *digestData = [NSData dataWithBytes:digest length:sizeof(digest)];
    return [digestData base64EncodedStringWithOptions:0];
}

static NSDictionary<NSString *, NSString *> *AppMetadata(NSString *appPath) {
    NSString *infoPath = [appPath stringByAppendingPathComponent:@"Contents/Info.plist"];
    NSData *data = [NSData dataWithContentsOfFile:infoPath];
    if (data == nil) {
        Fail(@"The application metadata is missing");
    }
    NSError *plistError = nil;
    NSDictionary *plist = [NSPropertyListSerialization propertyListWithData:data
                                                                    options:NSPropertyListImmutable
                                                                     format:nil
                                                                      error:&plistError];
    NSString *bundleIdentifier = plist[@"CFBundleIdentifier"];
    NSString *version = plist[@"CFBundleShortVersionString"];
    NSString *executable = plist[@"CFBundleExecutable"];
    if (bundleIdentifier.length == 0 || version.length == 0 || executable.length == 0) {
        Fail([NSString stringWithFormat:@"The application metadata is invalid: %@",
              plistError.localizedDescription ?: @"missing required fields"]);
    }
    NSString *executablePath = [[appPath stringByAppendingPathComponent:@"Contents/MacOS"]
        stringByAppendingPathComponent:executable];
    if (![[NSFileManager defaultManager] isExecutableFileAtPath:executablePath]) {
        Fail(@"The updated application executable is missing");
    }
    return @{@"bundleIdentifier": bundleIdentifier, @"version": version};
}

static NSString *FindExtractedApplication(NSString *directoryPath) {
    NSError *listError = nil;
    NSArray<NSString *> *entries = [[NSFileManager defaultManager]
        contentsOfDirectoryAtPath:directoryPath
                            error:&listError];
    if (entries == nil) {
        Fail([NSString stringWithFormat:@"Cannot inspect the extracted update: %@",
              listError.localizedDescription]);
    }
    NSMutableArray<NSString *> *applications = [NSMutableArray array];
    for (NSString *entry in entries) {
        NSString *candidate = [directoryPath stringByAppendingPathComponent:entry];
        BOOL isDirectory = NO;
        if ([entry.pathExtension.lowercaseString isEqualToString:@"app"]
            && [[NSFileManager defaultManager] fileExistsAtPath:candidate isDirectory:&isDirectory]
            && isDirectory) {
            [applications addObject:candidate];
        }
    }
    if (applications.count != 1) {
        Fail(@"The update archive must contain exactly one application bundle");
    }
    return applications.firstObject;
}

static void WaitForParentExit(pid_t parentPID, NSTimeInterval timeout) {
    Log([NSString stringWithFormat:@"Waiting for parent process %d to exit", parentPID]);
    NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:timeout];
    while ([deadline timeIntervalSinceNow] > 0) {
        errno = 0;
        if (kill(parentPID, 0) != 0 && errno == ESRCH) {
            Log(@"Parent process exited");
            return;
        }
        [NSThread sleepForTimeInterval:0.2];
    }
    Fail(@"Timed out waiting for CanvasHub to exit");
}

static void WriteState(
    NSDictionary<NSString *, id> *options,
    NSString *status,
    NSString *backupPath,
    NSString *errorMessage
) {
    NSDictionary *payload = @{
        @"status": status,
        @"expected_version": options[@"expectedVersion"],
        @"target_app": options[@"targetApp"],
        @"backup_app": backupPath ?: @"",
        @"error": errorMessage ?: @"",
        @"updated_at": [[[NSISO8601DateFormatter alloc] init] stringFromDate:[NSDate date]],
    };
    NSError *jsonError = nil;
    NSData *data = [NSJSONSerialization dataWithJSONObject:payload
                                                   options:NSJSONWritingPrettyPrinted | NSJSONWritingSortedKeys
                                                     error:&jsonError];
    if (data == nil) {
        Fail([NSString stringWithFormat:@"Cannot encode update state: %@",
              jsonError.localizedDescription]);
    }
    NSString *statePath = options[@"stateFile"];
    [[NSFileManager defaultManager] createDirectoryAtPath:[statePath stringByDeletingLastPathComponent]
                              withIntermediateDirectories:YES
                                               attributes:nil
                                                    error:nil];
    NSError *writeError = nil;
    if (![data writeToFile:statePath options:NSDataWritingAtomic error:&writeError]) {
        Fail([NSString stringWithFormat:@"Cannot write update state: %@",
              writeError.localizedDescription]);
    }
}

static void Relaunch(NSString *appPath) {
    Log([NSString stringWithFormat:@"Launching %@", appPath]);
    RunTask(@"/usr/bin/open", @[@"-n", appPath], NO);
}

static void SwapPaths(NSString *firstPath, NSString *secondPath, NSString *failurePrefix) {
    if (renameatx_np(
        AT_FDCWD,
        firstPath.fileSystemRepresentation,
        AT_FDCWD,
        secondPath.fileSystemRepresentation,
        RENAME_SWAP
    ) != 0) {
        Fail([NSString stringWithFormat:@"%@: %s", failurePrefix, strerror(errno)]);
    }
}

static void PerformUpdate(NSDictionary<NSString *, id> *options) {
    NSFileManager *fileManager = [NSFileManager defaultManager];
    NSString *targetApp = options[@"targetApp"];
    NSString *archive = options[@"archive"];
    if (![targetApp.pathExtension.lowercaseString isEqualToString:@"app"]) {
        Fail(@"The target path is not an application bundle");
    }
    if (![fileManager fileExistsAtPath:targetApp]) {
        Fail(@"The installed application cannot be found");
    }
    if (![fileManager fileExistsAtPath:archive]) {
        Fail(@"The downloaded update archive cannot be found");
    }

    NSDictionary *currentMetadata = AppMetadata(targetApp);
    if (![currentMetadata[@"bundleIdentifier"] isEqualToString:ExpectedBundleIdentifier]) {
        Fail(@"The installed application bundle identifier is not supported");
    }

    NSError *attributesError = nil;
    NSDictionary *attributes = [fileManager attributesOfItemAtPath:archive error:&attributesError];
    unsigned long long archiveSize = [attributes[NSFileSize] unsignedLongLongValue];
    if (attributes == nil || archiveSize != [options[@"expectedSize"] unsignedLongLongValue]) {
        Fail([NSString stringWithFormat:@"The downloaded update size does not match the release manifest: %@",
              attributesError.localizedDescription ?: @"size mismatch"]);
    }

    Log([NSString stringWithFormat:@"Verifying SHA-512 for %@", archive.lastPathComponent]);
    if (![ArchiveSHA512(archive) isEqualToString:options[@"expectedSHA512"]]) {
        Fail(@"The downloaded update checksum does not match the release manifest");
    }

    NSString *targetParent = targetApp.stringByDeletingLastPathComponent;
    NSString *transactionID = NSUUID.UUID.UUIDString.lowercaseString;
    NSString *stagingPath = [targetParent
        stringByAppendingPathComponent:[NSString stringWithFormat:@".canvashub-update-%@", transactionID]];
    NSString *backupPath = [targetParent
        stringByAppendingPathComponent:[NSString stringWithFormat:@".%@.backup-%@",
                                        targetApp.lastPathComponent, transactionID]];
    NSError *directoryError = nil;
    if (![fileManager createDirectoryAtPath:stagingPath
                withIntermediateDirectories:NO
                                 attributes:nil
                                      error:&directoryError]) {
        Fail([NSString stringWithFormat:@"Cannot create update staging directory: %@",
              directoryError.localizedDescription]);
    }

    @try {
        Log([NSString stringWithFormat:@"Extracting update into %@", stagingPath]);
        RunTask(@"/usr/bin/ditto", @[@"-x", @"-k", archive, stagingPath], NO);
        NSString *extractedApp = FindExtractedApplication(stagingPath);
        NSDictionary *updateMetadata = AppMetadata(extractedApp);
        if (![updateMetadata[@"bundleIdentifier"] isEqualToString:ExpectedBundleIdentifier]) {
            Fail(@"The update bundle identifier does not match CanvasHub");
        }
        if (![updateMetadata[@"version"] isEqualToString:options[@"expectedVersion"]]) {
            Fail([NSString stringWithFormat:@"The update version %@ does not match expected version %@",
                  updateMetadata[@"version"], options[@"expectedVersion"]]);
        }

        WaitForParentExit([options[@"parentPID"] intValue], 120);

        Log([NSString stringWithFormat:@"Atomically swapping %@ with %@", targetApp, extractedApp]);
        SwapPaths(targetApp, extractedApp, @"Cannot atomically install the update");

        @try {
            Log([NSString stringWithFormat:@"Moving the previous application to %@", backupPath]);
            NSError *moveError = nil;
            if (![fileManager moveItemAtPath:extractedApp toPath:backupPath error:&moveError]) {
                SwapPaths(targetApp, extractedApp, @"Cannot restore the application after backup failure");
                Fail([NSString stringWithFormat:@"Cannot preserve the previous application: %@",
                      moveError.localizedDescription]);
            }
            RunTask(@"/usr/bin/xattr",
                    @[@"-d", @"-r", @"com.apple.quarantine", targetApp],
                    YES);
            WriteState(options, @"installed", backupPath, nil);
            if ([options[@"relaunch"] boolValue]) {
                Relaunch(targetApp);
            }
            Log([NSString stringWithFormat:@"Update %@ installed successfully",
                 options[@"expectedVersion"]]);
        } @catch (NSException *exception) {
            Log([NSString stringWithFormat:@"Install failed, restoring backup: %@",
                 exception.reason]);
            if ([fileManager fileExistsAtPath:targetApp]
                && [fileManager fileExistsAtPath:backupPath]) {
                SwapPaths(targetApp, backupPath, @"Update failed and the previous application could not be restored");
                [fileManager removeItemAtPath:backupPath error:nil];
            }
            @throw;
        }
    } @finally {
        [fileManager removeItemAtPath:stagingPath error:nil];
    }
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        @try {
            NSDictionary<NSString *, id> *options = ParseArguments(NSProcessInfo.processInfo.arguments);
            LogFilePath = options[@"logFile"];
            Log([NSString stringWithFormat:@"CanvasHub updater %@ started for version %@",
                 UpdaterVersion, options[@"expectedVersion"]]);
            @try {
                PerformUpdate(options);
                return EXIT_SUCCESS;
            } @catch (NSException *exception) {
                NSString *message = exception.reason ?: @"Unknown update failure";
                Log([NSString stringWithFormat:@"Update failed: %@", message]);
                @try {
                    WriteState(options, @"failed", nil, message);
                } @catch (__unused NSException *stateException) {
                }
                if ([options[@"relaunch"] boolValue]
                    && [[NSFileManager defaultManager] fileExistsAtPath:options[@"targetApp"]]) {
                    @try {
                        Relaunch(options[@"targetApp"]);
                    } @catch (__unused NSException *launchException) {
                    }
                }
                return EXIT_FAILURE;
            }
        } @catch (NSException *exception) {
            fprintf(stderr, "CanvasHub updater: %s\n",
                    (exception.reason ?: @"Unknown argument failure").UTF8String);
            return EXIT_FAILURE;
        }
    }
}
